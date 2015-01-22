<?php
/**
 * Created by JetBrains PhpStorm.
 * Author: Ilya_TT (ilya.tt07@gmail.com)
 * Date: 21.01.15
 * Time: 1:41
 */

namespace Resume\ShopBundle\DataFixtures\ORM;

use Doctrine\Common\DataFixtures\FixtureInterface;
use Doctrine\Common\Persistence\ObjectManager;
use Resume\ShopBundle\Entity\Product;
use Resume\ShopBundle\Entity\Category;
use Resume\ShopBundle\Entity\Provider;

class LoadProductData implements FixtureInterface
{
	/**
	 * {@inheritDoc}
	 */
	public function load(ObjectManager $manager)
	{
		$demo = include 'demo.php';

		$repository_category = $manager->getRepository('ResumeShopBundle:Category');

		$repository_provider = $manager->getRepository('ResumeShopBundle:Provider');

		foreach($demo as $row){

			if(!($category1 = $repository_category->findOneByName($row['category1']))){
				$category1 = new Category();
				$category1->setName($row['category1']);
			}

			if(!($category2 = $repository_category->findOneByName($row['category2']))){
				$category2 = new Category();
				$category2->setName($row['category2']);
			}

			if(!($provider = $repository_provider->findOneByName($row['provider']))){
				$provider = new Provider();
				$provider->setName($row['provider']);
			}

			$product = new Product();
			$product->setName($row['product']);
			$product->setPrice($row['price']);
			$product->setImage($row['image']);
			$product->addCaterody($category1);
			$product->addCaterody($category2);
			$product->setProvider($provider);

			$manager->persist($category1);
			$manager->persist($category2);
			$manager->persist($provider);
			$manager->persist($product);

			$manager->flush();
		}
	}
}

