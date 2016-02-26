<?php

namespace Resume\ShopBundle\Entity;

use Doctrine\Common\Collections\ArrayCollection;
use Doctrine\ORM\Mapping as ORM;

/**
 * Product
 *
 * @ORM\Table()
 * @ORM\Entity(repositoryClass="Resume\ShopBundle\Entity\ProductRepository")
 */
class Product
{
    /**
     * @var integer
     *
     * @ORM\Column(name="id", type="integer")
     * @ORM\Id
     * @ORM\GeneratedValue(strategy="AUTO")
     */
    private $id;

    /**
     * @var string
     *
     * @ORM\Column(name="name", type="string", length=100, unique=true)
     */
    private $name;


    /**
     * @var string
     *
     * @ORM\Column(name="price", type="decimal", scale=2)
     */
    private $price;


	/**
	 * @var string
	 *
	 * @ORM\Column(name="image", type="string", length=255)
	 */
	private $image;


    /**
     * Get id
     *
     * @return integer 
     */
    public function getId()
    {
        return $this->id;
    }

    /**
     * Set name
     *
     * @param string $name
     * @return Product
     */
    public function setName($name)
    {
        $this->name = $name;

        return $this;
    }

    /**
     * Get name
     *
     * @return string 
     */
    public function getName()
    {
        return $this->name;
    }

    /**
     * Set price
     *
     * @param string $price
     * @return Product
     */
    public function setPrice($price)
    {
        $this->price = $price;

        return $this;
    }

    /**
     * Get price
     *
     * @return string 
     */
    public function getPrice()
    {
        return $this->price;
    }

	/**
	 *
	 * @ORM\ManyToOne(targetEntity="Provider", inversedBy="products")
	 * @ORM\JoinColumn(name="provider_id", referencedColumnName="id")
	 */
	protected $provider;

	/**
	 *
	 * @ORM\ManyToMany(targetEntity="Category", inversedBy="products")
	 * @ORM\JoinTable(name="products_caterodies")
	 */
	protected $caterodies;

	public function __construct()
	{
		$this->caterodies = new ArrayCollection();
	}


    /**
     * Set provider
     *
     * @param \Resume\ShopBundle\Entity\Provider $provider
     * @return Product
     */
    public function setProvider(\Resume\ShopBundle\Entity\Provider $provider = null)
    {
        $this->provider = $provider;

        return $this;
    }

    /**
     * Get provider
     *
     * @return \Resume\ShopBundle\Entity\Provider 
     */
    public function getProvider()
    {
        return $this->provider;
    }

    /**
     * Add caterodies
     *
     * @param \Resume\ShopBundle\Entity\Category $caterodies
     * @return Product
     */
    public function addCaterody(\Resume\ShopBundle\Entity\Category $caterodies)
    {
        $this->caterodies[] = $caterodies;

        return $this;
    }

    /**
     * Remove caterodies
     *
     * @param \Resume\ShopBundle\Entity\Category $caterodies
     */
    public function removeCaterody(\Resume\ShopBundle\Entity\Category $caterodies)
    {
        $this->caterodies->removeElement($caterodies);
    }

    /**
     * Get caterodies
     *
     * @return \Doctrine\Common\Collections\Collection 
     */
    public function getCaterodies()
    {
        return $this->caterodies;
    }

    /**
     * Set image
     *
     * @param string $image
     * @return Product
     */
    public function setImage($image)
    {
        $this->image = $image;

        return $this;
    }

    /**
     * Get image
     *
     * @return string 
     */
    public function getImage()
    {
        return $this->image;
    }
}
